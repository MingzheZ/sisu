from __future__ import unicode_literals

import sendgrid
import os
from sendgrid.helpers.mail import *

from django.shortcuts import render
from django.utils import timezone
from .models import Post, Comment, Category, AppPreferrence, PostPreferrence, ReplyToComment,Cluster
from .models import PollQuestions, PollAnswer
from django.shortcuts import render, get_object_or_404
from .forms import PostForm, CommentForm, ContactForm, SearchForm, ReplyToCommentForm
from django.shortcuts import redirect
from django.contrib.auth.decorators import login_required
from django.db import models
from django.core.mail import send_mail, BadHeaderError
from django.http import HttpResponse, HttpResponseRedirect, JsonResponse
from django.contrib import auth
from ipware import get_client_ip
from django.template import Context
import re
from django.db.models import Q
from django.contrib import messages
from django.db.models import Count
from users.models import CustomUser, UserProfile
from users.forms import CustomUserCreationForm, UserProfileForm
from django.template.loader import render_to_string
from django.forms.models import inlineformset_factory
from django.core.exceptions import PermissionDenied

from hitcount.models import HitCount
from hitcount.views import HitCountMixin

from .suggestions import update_clusters

import pygal
from .chart import CatPieChart, PollHorizontalBarChart
from django.views.generic import TemplateView
from pygal.style import DarkStyle


# Create your views here.

#
# Global variables across all templates
# 
def category(request):
  categories = Category.__members__.items()
  return {'categories' : categories}

  
# Popular cases
# list top 5 cases with the most comments
# get no. of comments for all posts
def popular_cases(request):
  
  cases = Comment.objects.filter(approved_comment=True).values('post').annotate(dcount=Count('post')).order_by('-dcount')

  size = Post.objects.all().count();
  
  count = 0;
  pop_posts = [];
  casesparsed = {};
  
  for case in cases:
    casesparsed[case['post']] = case['dcount']
    
    if count < 5:
      #print(case['post'])
      #print(Post.objects.filter(pk=case['post']))
      pop_posts.append(Post.objects.filter(pk=case['post']))
      count = count + 1;
  
  #print(casesparsed)
    
  return {'pop_cases' : pop_posts, 'cases':casesparsed}

# Recommendation
def user_recommendation_list(request):
  post_list = {}
  
  if request.user.is_authenticated:
    # get the user commented:
    user_commented = Comment.objects.filter(author=request.user.username).prefetch_related('post')
    user_metooed = PostPreferrence.objects.filter(vote_value=1, username=auth.get_user(request))
    
    user_commented_posts = set(map(lambda x: x.post.pk, user_commented))
    user_metooed_posts = set(map(lambda x: x.postpk.pk, user_metooed))
    
    #print (user_commented_posts)
    #print (user_metooed_posts)
    
    # the set of posts this user commented and metooed
    user_set = user_commented_posts | user_metooed_posts
    #print (recommend_set)
    
    #get user cluster name & get all other cluster members
    try:
       user_cluster = CustomUser.objects.get(username=auth.get_user(request)).cluster_set.first().name
    
    except: # if no cluster assigned for a user, update clusters
       update_clusters("true")
       user_cluster = CustomUser.objects.get(username=auth.get_user(request)).cluster_set.first().name
    
    user_cluster_other_members = Cluster.objects.get(name=user_cluster).users.exclude(username=auth.get_user(request)).all()
    other_members_usernames = set(map(lambda x: x.username, user_cluster_other_members))
    
    # get other users' commented and metooed posts from the same clusters
    other_user_commented_posts = Comment.objects.filter(author__in=other_members_usernames).exclude(post__pk__in=user_set)
    other_user_metooed_posts =  PostPreferrence.objects.filter(username__username__exact=other_members_usernames, vote_value=1).exclude(postpk__pk__in=user_set)        
    
    other_user_commented = set(map(lambda x: x.post.pk, other_user_commented_posts))
    other_user_metooed = set(map(lambda x: x.postpk.pk, other_user_metooed_posts))
    
    other_users_set = other_user_commented | other_user_metooed
    
    post_list_1 = list(Post.objects.filter(id__in=other_users_set))
    post_list_2 = list(Post.objects.exclude(id__in=user_set))
    
    post_list = list(set(post_list_1)|set(post_list_2))[:5]
    
    #print(post_list)
    #print(other_users_set)
    #print(other_members_usernames)
  
  return {'rec_post_list': post_list}
  
#
# For About us page
#
def about_sisu(request):
    context = {
        'signup_form': CustomUserCreationForm()
    }
    
    return render(request, 'blog/about.html', context)
    
def about_us(request):
    return render(request, 'blog/about_us.html')
    
def post_list(request):
    posts = Post.objects.filter(published_date__lte=timezone.now()).order_by('-published_date')
    
    return render(request, 'blog/post_list.html', {'posts':posts})
    
# Post.objects.get(pk=pk)
def post_cases(request):
    return render(request, 'blog/post_category_main.html')
    
def post_list_by_category(request, category_name):
    posts = Post.objects.filter(category_name=category_name).order_by('-published_date')
    cat = Category.get_label(category_name)
    return render(request, 'blog/post_list.html', {'posts':posts, 'cat':cat })

def post_detail(request, pk):
    post = get_object_or_404(Post, pk=pk)
    user_name = auth.get_user(request)
    ip = request.session['ip']
    
    hit_count = HitCount.objects.get_for_object(post)
    hit_count_response = HitCountMixin.hit_count(request, hit_count)    
    
    #print ("hit---- " + str(hit_count_response.hit_message))
    
    if request.user.is_authenticated:
        if PostPreferrence.objects.filter(username=user_name, ip_address=ip, postpk=pk, vote_value=1).exists():   
            voted = True
        else:
            voted = False
        
    else:
        if PostPreferrence.objects.filter(ip_address=ip, postpk=pk, vote_value=1).exists(): 
            voted = True
        else:
            voted = False   
    try:
        total_yes = PostPreferrence.objects.filter(vote_value=1, postpk=pk).count()
    except PostPreferrence.DoesNotExist:
        total_yes = 0;
    
    #Polling questions and stats
    if(PollAnswer.objects.filter(post=pk, user=user_name)).exists():
       pollquestion = get_object_or_404(PollQuestions, post=pk)
       polled = True
       
       bar_chart = PollHorizontalBarChart(print_values=True,value_formatter=lambda x: '{}%'.format(x),
                                          legend_at_bottom=True,
                                          legend_box_size=30,
                                          style=pygal.style.styles['default'](legend_font_size=30, 
                                                                              value_font_size=30, 
                                                                              label_font_size=25,
                                                                              ))
       chart = bar_chart.generate(pollquestion)
    
    else:
       pollquestion = get_object_or_404(PollQuestions, post=pk)
       polled = False
       chart = None
    
    summary = ({
        'voted':voted,
        'total_yes': total_yes,
        'polled': polled,
        'pollquestion': pollquestion,
    }) 
    
    return render(request, 'blog/post_detail_index.html', 
                  {'post': post, 
                   'summary': summary,
                   'barchart': chart,
                  })
    
@login_required
def post_new(request):
    if request.method == "POST":
        form = PostForm(request.POST)
        if form.is_valid():
            post = form.save(commit=False)
            post.author = request.user
            post.published_date = timezone.now()
            post.save()
            return redirect('post_detail', pk=post.pk)
    else:
        form = PostForm()
    return render(request, 'blog/post_edit.html', {'form': form})

@login_required   
def post_draft_list(request):
  posts = Post.objects.filter(published_date__isnull=True).order_by('created_date')
  return render(request, 'blog/post_draft_list.html', {'posts': posts})

@login_required  
def post_publish(request, pk):
    post = get_object_or_404(Post, pk=pk)
    post.publish_post()
    return redirect('post_detail', pk=pk)

@login_required    
def post_remove(request, pk):
    post = get_object_or_404(Post, pk=pk)
    post.delete()
    return redirect('post_list')

@login_required     
def post_edit(request, pk):

    post = get_object_or_404(Post, pk=pk)
    if request.method == "POST":
        form = PostForm(request.POST, instance=post)
        if form.is_valid():
            post = form.save(commit=False)
            post.author = request.user
            post.published_date = timezone.now()
            post.save()
            return redirect('post_detail', pk=post.pk)
    else:
        form = PostForm(instance=post)
    return render(request, 'blog/post_edit.html', {'form': form})

'''
@login_required     
def add_comment_to_post_orig(request, pk):
    post = get_object_or_404(Post, pk=pk)
    if request.method == "POST":
        form = CommentForm(request.POST)
        if form.is_valid():
            comment = form.save(commit=False)
            comment.post = post
            comment.save()
            messages.info(request, 'Thank you for your comment! It will be posted after censoring.')
            return redirect('post_detail', pk=post.pk)
    else:
        form = CommentForm()
    return render(request, 'blog/add_comment_to_post.html', {'form': form})

@login_required     
def add_reply_to_comment_orig(request, pk, cpk):
    post = get_object_or_404(Post, pk=pk)
    comment = get_object_or_404(Comment, post=post, pk=cpk)
    if request.method == "POST":
        form = ReplyToCommentForm(request.POST)
        if form.is_valid():
            replyToComment = form.save(commit=False)
            replyToComment.post = post
            replyToComment.comment = comment
            replyToComment.save()
            return redirect('post_detail', pk=post.pk)
    else:
        form = CommentForm()
    return render(request, 'blog/add_comment_to_post.html', {'form': form})
'''

@login_required     
def add_comment_to_post(request):
  
  if request.method == "GET":
     pid = request.GET['pid']
     author = request.GET['author']
     content = request.GET['text']
     
     commentpost = get_object_or_404(Post, pk=pid)
     
     comment = Comment()
     comment.post = commentpost
     comment.author = author
     comment.user = request.user
     
     userprofile = get_object_or_404(UserProfile, user=comment.user)
     comment.userprofile = userprofile
     
     comment.text = content
     
     comment.save()
    
     update_clusters("false")
           
  else:
     form = CommentForm()
    
  return render(request, 'blog/post_detail_index.html', {'post':commentpost})    
    
@login_required     
def add_reply_to_comment(request):
    
    if request.method == "GET":
        pid = request.GET['pid']
        cid = request.GET['cid']
        author = request.GET['author']
        content = request.GET['text']
        
        replypost = get_object_or_404(Post, pk=pid)
        comment = get_object_or_404(Comment, post=replypost, pk=cid)
        
        replyToComment = ReplyToComment()
        replyToComment.post = replypost
        replyToComment.comment = comment
        replyToComment.author = author
        replyToComment.text = content
        replyToComment.user = request.user
     
        userprofile = get_object_or_404(UserProfile, user=replyToComment.user)
        replyToComment.userprofile = userprofile
        
        replyToComment.save()
           
    else:
        form = CommentForm()
    return render(request, 'blog/post_detail_index.html', {'post':replypost})
    
@login_required
def comment_approve(request, pk):
    comment = get_object_or_404(Comment, pk=pk)
    comment.approve()
    return redirect('post_detail', pk=comment.post.pk)

@login_required
def comment_remove(request, pk):
    comment = get_object_or_404(Comment, pk=pk)
    comment.delete()
    return redirect('post_detail', pk=comment.post.pk)
#
# For contact us page
#
def contact_us(request):
    if request.method == 'GET':
        form = ContactForm()
    else:
        form = ContactForm(request.POST)
        if form.is_valid():
            sender = "From " + form.cleaned_data['your_name']
            if request.user.is_authenticated:
              sender = sender + "_(REG_User)_" + auth.get_user(request).username
            else:
              sender = sender + "_(PUB_User)_"
              
            sg = sendgrid.SendGridAPIClient(apikey=os.environ.get('SENDGRID_API_KEY'))
            from_email = Email(form.cleaned_data['your_email'])
            to_email = Email("sisu.contact.us@gmail.com")
            subject = sender + form.cleaned_data['subject']
            content = Content("text/plain", form.cleaned_data['message'])
            
            mail = Mail(from_email, subject, to_email, content)
            response = sg.client.mail.send.post(request_body=mail.get())
            '''print(response.status_code)
            print(response.body)
            print(response.headers) 
            '''
            '''
            from_email = form.cleaned_data['your_email']
            message = form.cleaned_data['message']
            try:
                send_mail(subject, message, from_email, ['admin@example.com'])
            except BadHeaderError:
                return HttpResponse('Invalid header found.')
                '''
            return render(request, 'blog/contact_us_success.html')
    return render(request, "blog/contact_us.html", {'form': form})
           
#
# For voting app
#
# check if the user / ip_address has voted 
def check_voted(request):
  voted = False;
  user_ip = get_client_ip(request)
  user_name = auth.get_user(request)
  ip = user_ip[0]
  
  request.session['ip'] = ip
  
  total_yes = AppPreferrence.objects.filter(vote_yes=1).count()
  total_no = AppPreferrence.objects.filter(vote_no=1).count()
  
   
  if request.user.is_authenticated:
     if AppPreferrence.objects.filter(username=user_name).exists():   
        voted = True
        
  else:
     if AppPreferrence.objects.filter(ip_address=ip).exists(): 
        voted = True
  
  summary = ({
      'voted':voted,
      'total_yes': total_yes,
      'total_no': total_no,
    })     
  return ({'summary': summary}) 

'''
# save the vote if never voted
def vote_for_app_orig(request, voted_value):
   
   if request.method == "POST":     
      user_preference = int(voted_value)
      #user_ip = get_client_ip(request)
      user_name = auth.get_user(request)
      ip = request.session['ip']
  
      app_voted = AppPreferrence() 
      app_voted.ip_address = ip
      
      if user_preference == 1:
          app_voted.vote_yes += 1
      elif user_preference == 2:
          app_voted.vote_no +=1
      
      if request.user.is_authenticated:
         #print("===================================" + str(user_preference) + str(ip) + str(user_name))
         app_voted.username = user_name
              
   app_voted.save()
     
   return render(request, "blog/about.html")
'''

def vote_for_app(request):
   
   if request.method == "GET":     
      user_preference = request.GET['voted_value']
      #user_ip = get_client_ip(request)
      user_name = auth.get_user(request)
      ip = request.session['ip']
  
      app_voted = AppPreferrence() 
      app_voted.ip_address = ip
      
      #print("==" + user_preference)
      
      if user_preference == "1":
          app_voted.vote_yes = 1
          
          
      elif user_preference == "2":
          app_voted.vote_no =1
      
      #print("=====" + str(app_voted.vote_yes))
      
      if request.user.is_authenticated:
         #print("===================================" + str(user_preference) + str(ip) + str(user_name))
         app_voted.username = user_name
              
   app_voted.save()
     
   return render(request, "blog/about.html")
   
def participate_poll(request):
   if request.method == 'GET':
      post_id = request.GET['postid']
      poll_value = request.GET['selected']
      user_name = auth.get_user(request)
      
      post = get_object_or_404(Post, pk=post_id)
      
      polledpost = PollAnswer()
      polledpost.post = post
      polledpost.user = user_name
      polledpost.choiceval = poll_value
      
      polledpost.save()
      
      pollquestion = get_object_or_404(PollQuestions, pk=post_id)
        
      if(poll_value == '1'):
         pollquestion.choice1stat += 1
      elif(poll_value == '2'):
         pollquestion.choice2stat += 1
      elif(poll_value == '3'): 
         pollquestion.choice3stat += 1
      elif(poll_value == '4'): 
         pollquestion.choice3stat += 1
        
      pollquestion.total += 1  
      pollquestion.save()            
        
      summary = ({
         'pollquestion':pollquestion,
      })
      
   return render(request, 'blog/post_detail_index.html', {'post':post, 'summary':summary})   

   
''' 
def on_off_star_orig(request, postid, on_off_value):
   
   if request.method == "POST":     
          
      post_preference = int(on_off_value)
      user_name = auth.get_user(request)
      ip = request.session['ip']
      
      post = get_object_or_404(Post, pk=postid)   
      
      try:
        if request.user.is_authenticated:
          postpreferrence_obj = PostPreferrence.objects.get(username=user_name, postpk=post, ip_address=ip)     
        else:
          postpreferrence_obj = PostPreferrence.objects.get(postpk=post, ip_address=ip)
        
        postpreferrence_obj.vote_value = post_preference
        postpreferrence_obj.save()       
        
        if post_preference == 2:
            voted = False
        else:
            voted = True
      
      except PostPreferrence.DoesNotExist:
        post_voted = PostPreferrence()
        post_voted.ip_address = ip
        post_voted.postpk = post
        post_voted.vote_value = post_preference 
      
        if request.user.is_authenticated:
          #print("===================================" + str(user_preference) + str(ip) + str(user_name))
          post_voted.username = user_name
        else:
          post_voted.username = None
          
        post_voted.save()   
        voted = True
   
      summary = ({
         'voted':voted,
         'total_yes': PostPreferrence.objects.filter(vote_value=1, postpk=postid).count(),
      })
      
   return render(request, 'blog/post_detail_index.html', {'post':post, 'summary':summary})
'''
   
def on_off_star(request):

   if request.method == 'GET':
      post_id = request.GET['postid']
      post_preference = request.GET['on_off_value']
      user_name = auth.get_user(request)
      ip = request.session['ip']
      likedpost = get_object_or_404(Post, pk=post_id)
   
      voted = True
      try:
        if request.user.is_authenticated:
          postpreferrence_obj = PostPreferrence.objects.get(username=user_name, postpk=likedpost, ip_address=ip)     
        else:
          postpreferrence_obj = PostPreferrence.objects.get(postpk=likedpost, ip_address=ip)
        
        postpreferrence_obj.vote_value = post_preference
        postpreferrence_obj.save()    
                
        
      except PostPreferrence.DoesNotExist:
        post_voted = PostPreferrence()
        post_voted.ip_address = ip
        post_voted.postpk = likedpost
        post_voted.vote_value = post_preference 
      
        if request.user.is_authenticated:
          #print("===================================" + str(user_preference) + str(ip) + str(user_name))
          post_voted.username = user_name
        else:
          post_voted.username = None
          
        post_voted.save()   
        voted = True
   
      summary = ({
         'voted':voted,
         'total_yes': PostPreferrence.objects.filter(vote_value=1, postpk=post_id).count(),
      })
      
      update_clusters("false")
      
   return render(request, 'blog/post_detail_index.html', {'post':likedpost, 'summary':summary})   
 
# Search Functionality
def normalize_query(query_string,
                    findterms=re.compile(r'"([^"]+)"|(\S+)').findall,
                    normspace=re.compile(r'\s{2,}').sub):
 
    return [normspace(' ', (t[0] or t[1]).strip()) for t in findterms(query_string)]

def get_query(query_string, search_fields):
    
    query = None # Query to search for every search term        
    terms = normalize_query(query_string)
    for term in terms:
        or_query = None # Query to search for a given term in each field
        for field_name in search_fields:
            q = Q(**{"%s__icontains" % field_name: term})
            if or_query is None:
                or_query = q
            else:
                or_query = or_query | q
        if query is None:
            query = or_query
        else:
            query = query & or_query
    return query
    
def search(request):
    query_string = ''
    found_entries = None
    
    if request.method == "POST":
       search_form = SearchForm(request.POST)
      
       if search_form.is_valid():
          query_string = search_form.cleaned_data['search_string']
          post_query = get_query(query_string, ['title', 'text', 'category_name'])
          found_entries = Post.objects.filter(post_query).order_by('-published_date')
            
    else:
       search_form = SearchForm()
    
    return render(request, 'blog/post_search_res.html',{ 'query_string': query_string, 'found_entries': found_entries })
###

#
# For User Settings
#
@login_required
def user_profile(request, pk):
    user = CustomUser.objects.get(pk=pk)
    user_form = UserProfileForm(instance=user)

    ProfileInlineFormset = inlineformset_factory(CustomUser, UserProfile, fields=('photo',))
    formset = ProfileInlineFormset(instance=user)

    if request.user.is_authenticated and request.user.id == user.id:
        if request.method == "POST":
            user_form = UserProfileForm(request.POST, request.FILES, instance=user)
            formset = ProfileInlineFormset(request.POST, request.FILES, instance=user)

            if user_form.is_valid():
                created_user = user_form.save(commit=False)
                formset = ProfileInlineFormset(request.POST, request.FILES, instance=created_user)

                if formset.is_valid():
                    created_user.save()
                    formset.save()
                    return render(request, "blog/user_settings_profile_upd.html")
            
            
        return render(request, "blog/user_settings.html", {
            "noodle": pk,
            "noodle_form": user_form,
            "formset": formset,
        })
    else:
        raise PermissionDenied
    #return render(request, 'blog/user_settings.html')
    
## Pie chart
class IndexView(TemplateView):
      template_name = 'blog/user_settings.html'
      
      def get_context_data(self, **kwargs):
          context = super(IndexView, self).get_context_data(**kwargs)
          user = self.request.user
          
          user_comments_approve = Comment.objects.filter(approved_comment=True, author=user).order_by('-created_date')
          user_comments_pending = Comment.objects.filter(approved_comment=False, author=user).order_by('-created_date')
          user_metooed = PostPreferrence.objects.filter(vote_value=1, username=user).order_by('-vote_date')
    
          user_comments = user_comments_approve | user_comments_pending
          
          # Get user profile info
          cus_user = CustomUser.objects.get(pk=user.pk)
          user_form = UserProfileForm(instance=cus_user)

          ProfileInlineFormset = inlineformset_factory(CustomUser, UserProfile, fields=('photo',))
          formset = ProfileInlineFormset(instance=cus_user)
          
          user_data = []
          for comment in user_comments:
            user_data.append(comment.post)
          
          for metoo in user_metooed:
            user_data.append(metoo.postpk)
          
          if len(user_data) != 0:
            cat_chart = CatPieChart(
                          height = 600,
                          width = 800,
                          explicit_size=True,
                          )
                          
            context['cat_chart'] = cat_chart.generate(user_data)
          
          else:
            context['cat_chart'] = None
            
          context['user_commented'] = user_comments_approve[:20]
          context['user_pending'] = user_comments_pending[:20]
          context['user_metooed'] = user_metooed
          context['noodle_form'] = user_form
          context['formset'] = formset
          
          return context